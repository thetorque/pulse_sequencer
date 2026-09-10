#!/usr/bin/env python3
"""
ddr3_sequencer_bringup.py -- Phase 6c first-light bring-up for the DDR3
sequencer path (ep00wire(5)=1).

This is the counterpart to ddr3_roundtrip_demo.py. Instead of just
round-tripping DDR3, it exercises the WHOLE Phase 6c chain on hardware:

    host writes a pulse program into DDR3  (write-assembler path)
        -> ddr3_line_streamer reads it back (ui_clk)
            -> line FIFO (fifo_128x4)
                -> pulse_sequencer pops 64-bit lines (clk_100)
                    -> master_logic / logic_out / led_ext

It writes a deliberately SLOW program -- state changes one second apart --
so you can watch master_logic (WireOut 0x2B) advance in real time and see
led_ext[0..3] walk, exactly like loop_test_demo. A --fast flag instead
loads the sim's tight {t=3,8,10}-tick demo for a scope / logic analyzer.

Pulse-line format (see memory/pulse-sequence-ram-format): a 64-bit line is
  channel = bits[31:0], time = bits[61:32] (ABSOLUTE cumulative tick of the
  state change), terminator = the all-zero line. A line's channel is held
  until the NEXT line's time. tick = 4*clk_100 = 40 ns => 25e6 ticks / s.

Control bits (ep00wire), status (WireOut), reset (TriggerIn 0x40 bit 0):
  bit1 infinite loop, bit2 start, bit3 line-trigger en, bit4 write/read
  mode (0=write), bit5 DDR3-sequencer mode. 0x2B = logic_out (= master_logic
  when the ep02/ep03 override mux is off). 0x2C bit16 = seq_done, [15:0] =
  seq_count.

Why no --sacrifice-beat0 here: the program lives at DDR3 address 0, inside
the low 32 KiB that is structurally immune to the cold-start row mis-address
(app_addr bit 14 is 0 there and the fault only ever CLEARS bit 14) -- see
memory/ddr3-read-adapter-design. So the streamer's initial prime read of the
program is safe without a sacrificial dummy.

Usage:
    python ddr3_sequencer_bringup.py <path-to-photon.bit> [--fast]

Requires the Opal Kelly `ok` FrontPanel Python module and, alongside it,
ddr3_roundtrip_demo.py (this script imports its proven connect / write /
read / reset helpers rather than re-implementing the MIG handshakes).
"""

import sys
import time

import ok
from ddr3_roundtrip_demo import connect, reset_ddr3, write_words, read_words

# ---- ep00wire control bits -------------------------------------------------
INFINITE_BIT = 1 << 1   # ep00wire(1): pulser_infinite_loop
START_BIT    = 1 << 2   # ep00wire(2): pulser_start_bit
LINETRIG_BIT = 1 << 3   # ep00wire(3): line-trigger enable
READMODE_BIT = 1 << 4   # ep00wire(4): 0 = write mode, 1 = read mode
SEQMODE_BIT  = 1 << 5   # ep00wire(5): 1 = DDR3 sequencer, 0 = legacy pulser_ram

# ---- status / reset --------------------------------------------------------
LOGIC_WIRE   = 0x2B     # ep2Bwire = logic_out (= master_logic, overrides off)
SEQ_WIRE     = 0x2C     # ep2Cwire: bit16 = seq_done, bits[15:0] = seq_count
SEQ_DONE_BIT = 1 << 16
RESET_TRIG_ADDR = 0x40  # TriggerIn 0x40
RESET_TRIG_BIT  = 0     # bit 0: pulser_counter_reset

TICKS_PER_SEC = 25_000_000   # tick = 40 ns

# streamer PRIME_BEATS=8 -> 16 lines primed before it reports ready; pad the
# program to that so the whole primed window is program + terminators, never
# stale DDR3 content.
PRIME_LINES = 16


def line(time_ticks, channel):
    """Pack one 64-bit pulse line: time in bits[61:32], channel in [31:0]."""
    return ((time_ticks & 0x3FFFFFFF) << 32) | (channel & 0xFFFFFFFF)


def build_program(fast):
    """The bring-up program as an ordered list of 64-bit lines, terminator
    included, padded to PRIME_LINES with terminators (even count)."""
    if fast:
        # sim PROG_SEL=0 demo: tight absolute ticks, for a scope / LA.
        lines = [line(3, 0x01), line(8, 0x02), line(10, 0x04), 0x0]
        expected = [0x01, 0x02, 0x04]
    else:
        # host-observable: one state per second so master_logic / led_ext can
        # be watched live. A line's channel holds until the NEXT line's time,
        # so each of 0x01/0x02/0x04/0x08 is held a full second; the 5 s line
        # turns everything off, then the terminator ends the run.
        lines = [
            line(1 * TICKS_PER_SEC, 0x01),
            line(2 * TICKS_PER_SEC, 0x02),
            line(3 * TICKS_PER_SEC, 0x04),
            line(4 * TICKS_PER_SEC, 0x08),
            line(5 * TICKS_PER_SEC, 0x00),   # all-off (real line, not terminator)
            0x0,                              # terminator -> seq_done
        ]
        expected = [0x01, 0x02, 0x04, 0x08]
    while len(lines) < PRIME_LINES:
        lines.append(0x0)                     # pad with terminators (even count)
    return lines, expected


def set_ep00(xem, value):
    """Drive ep00wire to an absolute value (all bits) and commit."""
    xem.SetWireInValue(0x00, value, 0xFFFFFFFF)
    xem.UpdateWireIns()


def pulse_reset(xem):
    xem.ActivateTriggerIn(RESET_TRIG_ADDR, RESET_TRIG_BIT)  # pulser_counter_reset


def main():
    args = sys.argv[1:]
    fast = "--fast" in args
    args = [a for a in args if a != "--fast"]
    if not args:
        sys.exit("usage: python ddr3_sequencer_bringup.py <photon.bit> [--fast]")
    bit_path = args[0]

    xem = connect(bit_path)   # ConfigureFPGA + wait for MIG calibration

    # Clean control state: every ep00 bit low, per-channel override mux off
    # (so logic_out == master_logic), loop limit 0 (one-shot).
    set_ep00(xem, 0x00000000)
    xem.SetWireInValue(0x02, 0, 0xFFFFFFFF)   # ep02: override enables off
    xem.SetWireInValue(0x03, 0, 0xFFFFFFFF)   # ep03: override values off
    xem.SetWireInValue(0x05, 0, 0xFFFFFFFF)   # ep05: loop_limit 0
    xem.UpdateWireIns()

    prog, expected = build_program(fast)
    mode = "fast (scope/LA)" if fast else "slow (host-observable, 1 s/state)"
    print(f"\n--- Phase 6c DDR3 sequencer bring-up: {mode} ---")

    # 1) Write the program into DDR3 at address 0 (write mode, pointers reset).
    reset_ddr3(xem)
    write_words(xem, prog)
    print(f"  wrote {len(prog)} lines to DDR3 @ address 0")

    # 2) Read it back through the (proven) read path to confirm the write
    #    landed before we trust the streamer. Address 0 is cold-start immune,
    #    so no sacrifice is needed.
    reset_ddr3(xem)
    got = read_words(xem, len(prog))
    if got == prog:
        print("  readback verify: DDR3 contents match the program  [OK]")
    else:
        print("  readback verify: MISMATCH -- the WRITE path is wrong, not the")
        print("  streamer. First differences (index: wrote -> read):")
        shown = 0
        for i, (w, r) in enumerate(zip(prog, got)):
            if w != r:
                print(f"    [{i}] {w:#018x} -> {r:#018x}")
                shown += 1
                if shown >= 6:
                    break
        sys.exit("aborting: fix the write path before bringing up the stream")

    # 3) Enter DDR3 sequencer mode and run.
    #    Leave write mode (bit4=0): while streaming, the mux hands MIG's command
    #    channel to the streamer, and the write path sits idle (write FIFO empty).
    set_ep00(xem, SEQMODE_BIT)                 # seq mode on, start still off
    pulse_reset(xem)                           # reset the sequencer FSM
    set_ep00(xem, SEQMODE_BIT | START_BIT)     # start -> streamer primes, seq runs
    print("  DDR3 sequencer started (ep00 bit5=seq mode, bit2=start)")
    print("  watch led_ext[0..3] walk; polling master_logic (0x2B) / seq_done (0x2C)\n")

    # 4) Poll master_logic + seq_done and log every change.
    observed = []          # nonzero master_logic values, in order of appearance
    prev = None
    done = False
    seq_count = 0
    t0 = time.time()
    timeout = 3.0 if fast else 8.0
    while time.time() - t0 < timeout:
        xem.UpdateWireOuts()
        logic = xem.GetWireOutValue(LOGIC_WIRE)
        seq = xem.GetWireOutValue(SEQ_WIRE)
        seq_count = seq & 0xFFFF
        if logic != prev:
            t = time.time() - t0
            print(f"    t={t:5.2f}s  master_logic=0x{logic:08x}  led_ext[5:0]={logic & 0x3f:06b}")
            if logic != 0 and (not observed or observed[-1] != logic):
                observed.append(logic)
            prev = logic
        if seq & SEQ_DONE_BIT:
            print(f"    t={time.time() - t0:5.2f}s  seq_done asserted (seq_count={seq_count})")
            done = True
            break
        time.sleep(0.02 if fast else 0.1)

    # 5) Stop and clear control state.
    set_ep00(xem, 0x00000000)

    # 6) Verdict.
    print("\n--- Bring-up result ---")
    print(f"  observed nonzero states, in order: {[hex(v) for v in observed]}")
    print(f"  expected:                          {[hex(v) for v in expected]}")
    if fast:
        # Too quick to catch the intermediate states by host polling; the
        # meaningful check is that the sequencer ran to completion.
        if done:
            print("  RESULT: PASS -- DDR3 sequencer ran the program to seq_done.")
            print("  (fast mode: put a scope/LA on led_ext[0..2] to see the "
                  "40 ns-scale 0x01/0x02/0x04 pulses.)")
        else:
            sys.exit("  RESULT: FAIL -- seq_done never asserted (see notes below).")
    else:
        if observed == expected and done:
            print("  RESULT: PASS -- the DDR3-streamed program produced the exact "
                  "expected waveform, in order, and finished.")
        elif observed and observed == expected[:len(observed)] and not done:
            sys.exit("  RESULT: PARTIAL -- states so far are correct but the run "
                     "did not reach seq_done within the timeout.")
        else:
            print("  RESULT: FAIL -- observed waveform does not match. Notes:")
            print("   * all-zero / no transitions => streamer never primed "
                  "(program not read from DDR3), or start/seq-mode not asserted.")
            print("   * scrambled channels/times  => 64-bit line half-order out "
                  "of the streamer FIFO differs from the write packing "
                  "(the Phase 6c analogue of the Phase 6b byte-order match).")
            sys.exit(1)


if __name__ == "__main__":
    main()
