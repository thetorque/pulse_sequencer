#!/usr/bin/env python3
"""
run_sequence.py -- build a named-channel TTL sequence, compile it, and run it
on the XEM7305. This is the ergonomic top of the headless stack (hwconfig ->
Sequence -> Driver) and the first hardware exercise of the M2 compiler through
the driver.

    python -m pulser3.run_sequence <photon.bit>            # run the built-in demo once
    python -m pulser3.run_sequence <photon.bit> --loops 5  # finite loop
    python -m pulser3.run_sequence <photon.bit> --infinite # loop until Ctrl-C
    python -m pulser3.run_sequence --list-channels          # print the channel map
    python -m pulser3.run_sequence --human                  # print the demo program, no HW

The demo staircases channels 0..5 (all watchable on led_ext / master_logic) so
you can see the pattern walk across the LEDs.
"""
import argparse
import sys
import time

from . import Driver
from . import hwconfig


def build_demo():
    """A staircase of overlapping 1.5 s pulses on the six lowest channels, then
    extended to 5 s. Returns the Sequence."""
    seq = hwconfig.new_sequence()
    staircase = [
        ('ttl_0',           0.0),
        ('sMOT_PROBE',      0.5),
        ('sMOT_PROBE_SPIN', 1.0),
        ('BIG_MOT_SH',      1.5),
        ('sMOT_AO',         2.0),
        ('BIG_MOT_AO',      2.5),
    ]
    for name, start in staircase:
        seq.add_pulse(name, start, 1.5)
    seq.extend_length(5.0)
    return seq


def print_channels():
    print("channel name -> number:")
    for name, num in sorted(hwconfig.CHANNELS.items(), key=lambda kv: (kv[1], kv[0])):
        print(f"  {num:2d}  {name}")


def print_human(seq):
    print("compiled program (time_s, channel_int, bits[ch0..chN-1]):")
    for t, ci, bits in seq.human_readable():
        print(f"  {t:8.3f} s   0x{ci:08X}   {bits}")
    print(f"  -> {len(seq.to_lines())} lines incl. terminator")


def main(argv=None):
    ap = argparse.ArgumentParser(description="pulser3 named-channel runner")
    ap.add_argument("bit", nargs="?", help="path to photon .bit (omit with --list-channels/--human)")
    ap.add_argument("--list-channels", action="store_true", help="print the channel map and exit")
    ap.add_argument("--human", action="store_true", help="print the compiled demo program and exit (no hardware)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--infinite", action="store_true", help="loop forever")
    g.add_argument("--loops", type=int, metavar="N", help="loop N times")
    args = ap.parse_args(argv)

    if args.list_channels:
        print_channels()
        return 0

    seq = build_demo()
    if args.human:
        print_human(seq)
        return 0

    if not args.bit:
        ap.error("bit path required (unless --list-channels/--human)")

    lines = seq.to_lines()
    expect_lc = len(lines)            # popped lines this pass = real program incl. terminator

    d = Driver()
    print(f"Connecting and configuring {args.bit} ...")
    d.connect(args.bit)
    d.load_program(lines, verify=True)
    print(f"Loaded demo sequence: {len(seq.switching_times)} switching times, "
          f"{expect_lc} lines (incl. terminator).")

    if args.infinite:
        print("Starting INFINITE loop -- watch the LEDs; Ctrl-C to stop.")
        d.start_infinite()
        try:
            last = -1
            while True:
                c = d.seq_count()
                if c != last:
                    print(f"  iterations: {c}   logic=0x{d.logic_out():08X}")
                    last = c
                time.sleep(0.2)
        except KeyboardInterrupt:
            d.stop()
            print(f"\nStopped after {d.seq_count()} iterations.")
        return 0

    if args.loops:
        print(f"Starting {args.loops} loops ...")
        d.start_number(args.loops)
        ok = d.wait_done(timeout=90.0)
        cnt, lc, ovf = d.seq_count(), d.line_count(), d.overflow()
        good = ok and cnt == args.loops and not ovf and lc == args.loops * expect_lc
        print(f"  done={ok}  seq_count={cnt}/{args.loops}  "
              f"line_count={lc} (expect {args.loops * expect_lc})  drop={ovf}")
        print("  RESULT:", "PASS" if good else "FAIL")
        return 0 if good else 1

    print("Starting SINGLE run ...")
    d.start_single()
    ok = d.wait_done(timeout=30.0)
    lc, ovf, logic = d.line_count(), d.overflow(), d.logic_out()
    good = ok and not ovf and lc == expect_lc and logic == 0x000
    print(f"  done={ok}  line_count={lc} (expect {expect_lc})  "
          f"drop={ovf}  final_logic=0x{logic:08X} (expect 0x00000000)")
    print("  RESULT:", "PASS" if good else "FAIL")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
